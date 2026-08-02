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

Packaged catalogue generation has two regimes, keyed on whether the provider has both a committed
native table and origin declarations.

The committed native table carries provenance. Produce it with the provider's `refresh` operation
against the live provider API. It may instead be materialized from a `tests/test_data/` fixture only
when that fixture has been verified content-identical to a live payload and the repository record
states the source URL, retrieval instant, canonicalization method, and digest. Nothing unattested
may enter the repository from a fixture.

+An orchestrator may also perform a live fetch outside a network-disabled executor and supply the
complete response as a step input. This route is sanctioned only when the same repository record
contains every exact request URL, one UTC retrieval instant, the accepted row and station counts,
the deterministic canonicalization and ordering rules, SHA-256 evidence, and a semantic frame
comparison between the committed native content and a fresh materialization of the complete supplied
response.

- USGS native-table attestation: the orchestrator made the following 102 requests for the ordered
  51-code (50 states plus DC) `_US_STATE_CODES` scope at `2026-08-02T01:14:11Z`:

- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AL&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AL&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AK&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AK&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AZ&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AZ&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AR&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AR&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CO&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CO&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CT&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CT&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=DE&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=DE&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=FL&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=FL&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=GA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=GA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=HI&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=HI&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ID&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ID&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IL&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IL&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IN&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IN&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=KS&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=KS&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=KY&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=KY&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=LA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=LA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ME&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ME&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MD&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MD&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MI&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MI&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MN&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MN&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MS&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MS&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MO&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MO&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MT&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MT&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NE&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NE&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NV&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NV&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NH&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NH&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NJ&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NJ&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NM&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NM&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NY&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NY&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NC&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NC&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ND&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ND&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OH&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OH&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OK&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OK&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OR&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OR&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=PA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=PA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=RI&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=RI&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=SC&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=SC&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=SD&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=SD&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=TN&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=TN&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=TX&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=TX&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=UT&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=UT&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=VT&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=VT&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=VA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=VA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WV&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WV&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WI&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WI&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WY&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WY&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=DC&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=DC&siteOutput=expanded`

  The [USGS Site Service documentation](https://waterservices.usgs.gov/docs/site-service/site-service-details/)
  states that `hasDataTypeCd` selects sites, `seriesCatalogOutput=true` returns period-of-record
  rows, and `siteOutput=expanded` cannot be combined with `seriesCatalogOutput=true`. The complete
  supplied response contained 55 codes and 110 files. Every entry passed `MANIFEST.sha256`; the
  manifest's SHA-256 is `d29ee34feaef0dda458c369ed5448e96b7e8b7064176a5f94360881b6cbdf34a`.
  The exact 102 consumed manifest lines have SHA-256
  `e197d3d5eb6f971e631693d7d6e2b26d1c7b7031850d62ed11f5891011dbc6bc`.

  The accepted 51-code scope has 26,258 stations in each pass, 2,036,546 series rows, zero
  cross-pass orphans, only `NAD83` in `dec_coord_datum_cd`, and both `dv` and `uv` source
  rows. The excluded `GU`, `MP`, `PR`, and `VI` files account for 275 stations. The complete
  supplied 55-code census has 26,533 stations in each pass, 2,055,307 series rows, and zero
  cross-pass orphans.

  Canonicalization keeps all 42 expanded fields as exact scalar strings; checks the twelve repeated
  series-pass station fields byte-for-byte against them; retains the twelve series-only fields as
  aligned `List(String)` columns; preserves duplicate complete series rows; sorts complete
  24-field series rows lexicographically in source header order within each station; sorts stations
  by exact `site_no`; and appends the single UTC-microsecond `retrieved_at`. No field is trimmed,
  renamed, parsed, converted, or harmonized. The compact UTF-8 JSON list of sorted `site_no`
  values, serialized with separators `(",", ":")` and `ensure_ascii=False`, has SHA-256
  `8ad79dac66b25a9dc46ebd30b650c1e647b44d9b31c9bc4fdd17c5e46f4ee241`. A fresh reconstruction
  from the attested response was compared with the committed native table using exact semantic frame
  equality; Parquet byte equality is not the provenance criterion.


### 4.1 Providers with a committed native table and origins

For a provider with both a committed native table and origin declarations (currently `lt_lhmt`
alone), the four canonical packaged catalogue artifacts (`catalogue/provider.json`,
`catalogue/products.parquet`, `catalogue/stations.parquet`, and
`catalogue/station_products.parquet`) are a pure, network-free function of that committed table and
the provider's origins. Generating the canonical artifacts from a live API is forbidden because it
would reintroduce the nondeterminism the pure build removes.

- Lithuania native-table attestation: the orchestrator performed
  `GET https://api.meteo.lt/v1/hydro-stations` outside the executor sandbox at
  `2026-08-01T18:31:08Z`, received 97 stations, and verified the live payload content-identical to
  `tests/test_data/lithuania_metadata_stations.json`. Canonicalization sorts stations by `code`,
  serializes JSON with sorted object keys and compact separators `(",", ":")` using Python's
  default `ensure_ascii=True`, UTF-8 encodes the result, and takes SHA-256; both inputs produced
  `02d16a6e872939b43ee7ae6d1c54e00b6b924f3d9a3f9a7553fc13680edc12d8`.

After writing provider code and tests, run that provider's network-free build from its committed
native table and origins, and commit the resulting canonical artifacts alongside the code.

### 4.2 Providers not yet migrated

For a provider without both a committed native table and origin declarations (currently the other
twelve), the four canonical packaged catalogue artifacts must be generated from the live provider
API before the provider is committed.

- `tests/test_data/<provider>_metadata_*.json` is a test fixture used for offline tests. It must
  never be used to generate the four canonical packaged catalogue artifacts.
- After writing all provider code and tests, run
  `generate_catalogue.py --live --out src/rivretrieve/_internal/providers/<provider>/catalogue/` to
  produce the four canonical packaged artifacts.

Commit the resulting artifacts alongside the code in both regimes. Regime 4.1 expands as each
provider milestone migrates; this distinction disappears once all thirteen providers have migrated.

Some generators include a provider-specific minimum-station guard that raises `FatalContractError`
when `--live` returns an implausibly small count, catching silent fetch failures or accidental
fixture-backed invocations. The threshold is calibrated per provider (e.g. 10 000 for USGS which has
26 000+ gauges; Lithuania has only 97 stations so no such guard is needed there). Do not copy a
numeric threshold from one provider to another.

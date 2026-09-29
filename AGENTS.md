# Project Instructions

## Purpose

RivRetrieve provides faithful, traceable access to river-gauge data from national hydrology agencies through one consistent shape. It harmonises objective identity and physics while leaving source judgement uninterpreted. See [architecture](docs/architecture.md) for responsibilities and stage contracts.

## Python environment

Use `uv` exclusively for project dependencies and execution.

- Add dependencies: `uv add <package>`; development dependencies: `uv add --dev <package>`.
- Sync the environment: `uv sync`.
- Run commands: `uv run <command>`.
- Run tests: `uv run pytest`.
- Format: `uv run ruff format`.
- Lint: `uv run ruff check --fix`.
- Type-check: `uv run ty check src`.

The normal type-check target is `src`. `tests/typecheck/nominal_window_misuse.py` is an intentional negative fixture exercised by the engine-contract tests. Do not suppress it.

## Library boundaries and types

Give each module a clear responsibility and pass only the dependencies its operations need, rather than broad configuration objects. Mathematical notation is optional when it clarifies a computation; module docstrings do not require mathematical signatures.

Resolve configuration, environment variables, paths, and resource wiring at explicit composition boundaries, including public library APIs as well as CLI entry points. Lower-level operations receive resolved dependencies instead of discovering application state themselves.

Parse external inputs at the boundary where they arrive, including provider responses received after API composition. Use domain types for identifiers, physical quantities, and configuration where invariants or units matter. Keep units explicit and preserve typed stage contracts. Do not wrap every value or bulk array; retain library carriers such as Polars frames and xarray datasets.

Represent named domain states with enums or literals, not ambiguous booleans. Incidental boolean flags do not need domain wrappers.

## Source fidelity and failures

Preserve source facts, vocabulary, and unknowns. Do not infer source judgement, time zones, or temporal support, or invent unpublished hydrological products. Do not substitute defaults for required inputs. Keep null values, absent rows, and failed requests distinct.

Raise on fatal internal contract errors; caller issue policy must not hide invalid stage output. Retain supported source failures as issues at the established isolation boundaries so independent series can still return results. Preserve the failure's identity and reason alongside those results. Do not silently log and continue or replace this partial-result model with a blanket crash rule.

## Public API docstrings

Use NumPy-style docstrings where public interfaces need explanation.
Apply this rule to public functions and user-facing returned types, methods,
and attributes, including those implemented under `_internal`.

Use judgement. If the name and signature fully explain an interface, no
docstring or prose summary is required. Do not add text or sections solely
for coverage or repeat information already clear from the signature.

Document what readers need to use and interpret the interface correctly:
non-obvious constraints, units, return contents, side effects, and failure
behavior. Include only applicable sections. A one-line summary is enough
when no further explanation is needed. Add examples when they clarify use.

All docstring prose must follow `docs/AGENTS.md`. Keep documentation accurate
when changing an interface.

## Verification evidence

Use [the maintainer guide](docs/maintenance/evidence.md) for verification and the
private [source archive](https://github.com/RivRetrieve/verification-evidence)
for retained material, exact collection selection and archive operations. Changes to governing claims, source bindings,
verifiers or collections require the applicable full checks against genuine inputs.
Report unavailable mandatory evidence as blocked; do not weaken checks or substitute
derived data for originals. Keep controlled material and credentials out of public
repositories, logs, caches, artifacts and distribution packages.

## Contributing tests

Before adding a test, check existing coverage and identify the distinct behavior or
architectural rule it protects. Use focused tests for edge cases, and explain why expensive
end-to-end combinations need separate coverage. Reuse expensive unchanged inputs only when
tests remain isolated and changed or corrupt inputs still reach validation. Measure and report
the runtime impact of costly new coverage. Lock exact wording or code structure only when that
property is an intentional contract.

## Complex-data assertions

Prefer library-specific assertions over manual element-by-element checks of structure or values:

```python
np.testing.assert_allclose(result, expected)
xr.testing.assert_identical(result, expected)
pl_testing.assert_frame_equal(result_df, expected_df)
```
